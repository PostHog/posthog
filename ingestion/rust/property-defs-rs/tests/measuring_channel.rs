use property_defs_rs::measuring_channel::measuring_channel;

// The in-flight counter is unsigned, so a decrement landing before its matching increment wraps it
// to usize::MAX, where the gauge then stays for the life of the process. That is what the
// production gauge was doing.
//
// This is a stress test, not a deterministic one: the window only exists across threads, so it
// takes a real multi-threaded interleaving to hit. Measured over 12 runs each way it catches the
// old ordering 11 times and never fails against the current one. It is a few milliseconds, so the
// occasional miss is worth having it in the suite. It cannot false-fail: the bound below is a hard
// ceiling on a correct implementation, not a timing guess.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_in_flight_count_never_underflows_under_interleaved_send_and_recv() {
    const CAPACITY: usize = 8;
    const ROUNDS: usize = 2_000;

    let (tx, mut rx) = measuring_channel::<u64>(CAPACITY);

    let sender = tokio::spawn({
        let tx = tx.clone();
        async move {
            for i in 0..ROUNDS as u64 {
                tx.send(i).await.expect("receiver alive");
            }
        }
    });

    for _ in 0..ROUNDS {
        rx.recv().await.expect("sender alive");
        // A message is counted from submission, so the queued messages plus the one sender
        // currently blocked inside send() is the true ceiling. What this is really watching for is
        // a wrapped counter, which lands near usize::MAX and is nowhere near this bound.
        let in_flight = rx.get_inflight_messages_count();
        assert!(
            in_flight <= CAPACITY + 1,
            "in-flight count {in_flight} is above the ceiling, so the counter wrapped"
        );
    }

    sender.await.expect("sender panicked");
    assert_eq!(
        rx.get_inflight_messages_count(),
        0,
        "every sent message was received, so the counter must be back to zero"
    );
}

// A send that fails never reaches the channel, so it must not leave a phantom message counted.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn test_failed_send_does_not_leak_an_in_flight_count() {
    let (tx, rx) = measuring_channel::<u64>(1);

    tx.try_send(1).expect("first send fits");
    assert!(tx.try_send(2).is_err(), "channel should be full");
    assert_eq!(tx.get_inflight_messages_count(), 1);

    drop(rx);
    assert!(tx.send(3).await.is_err(), "receiver is gone");
    assert_eq!(
        tx.get_inflight_messages_count(),
        1,
        "a send to a closed channel must not be counted"
    );
}
