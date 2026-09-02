# personhog coordination invariants

The invariants a review prompt should hand to a cold-context reviewer.
Verify against `rust/personhog-coordination/` — this list summarizes; the
code and its README are authoritative.

1. **Serving authority ⇔ live lease-backed registration.** A pod serves a
   partition exactly while its etcd registration, backed by a renewed
   lease, stands behind it. Anything serving without that is a zombie;
   anything registered but refusing to serve is a black hole (the
   coordinator will not reassign what a live owner holds).
2. **Acked ⇒ durable.** The leader's produce path awaits Kafka delivery
   before acking, so "no in-flight handlers" implies "every acked write
   is durably in the changelog." Every drain and fence argument leans on
   this.
3. **The dead-owner path has no fence.** When a registration disappears,
   the coordinator reassigns with no old-owner acks — its safety rests
   entirely on a deregistered owner being unable to produce. Therefore:
   nothing may deregister a pod (revoke its lease) while it can still
   serve; the local self-fence must complete first.
4. **Fence-before-move.** A pod that loses its lease must stop
   admissions, drain in-flights, and release _before_ the coordinator can
   treat the lease as expired. The keepalive's renewal margin reserves
   the final third of the TTL for exactly this; the fence's drain bound
   must fit inside it.
5. **Handoff phases gate traffic.** Freezing → Draining advances only
   after every registered router freeze-acks (and stashes); Draining →
   Warming only after the old owner's drained-ack (live-owner path);
   routers flip to the new owner only at Complete. No single router ever
   writes to both owners; dual-write requires a router that missed the
   freeze — the documented double-zombie residual.
6. **Warming reads a stable HWM.** By Warming, no router produces to the
   partition, so the changelog HWM the warm snapshots is final. Writes
   landing after a new owner's snapshot are invisible to it forever —
   the write-loss shape most findings reduce to.
7. **Convergence is level-triggered and single-flight per partition.**
   Watch events are signals to re-read durable state, never payloads to
   act on; missed or reordered events are healed by reconcile passes. At
   most one convergence per partition runs at a time; convergences for
   different partitions may run concurrently.
8. **Warms are cancellation-atomic.** A warm may be dropped mid-flight
   and re-invoked; it must leave no observable partial state (buffer,
   install atomically). A cancelled warm is never released — the pod
   tracks a warm only once it returns.
9. **Budgets bound wedges, not lifetimes.** Consecutive-failure budgets
   escalate to process restart; the reset requires _applied work_
   (a handler invoked, state changed), never elapsed time or successful
   reads. Reconcile-failure tolerance bounds staleness at one tick per
   count and must not be exempt from escalation via its own detection
   duration.
10. **Known residuals are documented, not denied.** The double-zombie
    write-loss path (pending epoch fencing), the pre-detection window of
    at most one keepalive round, and the in-flight-at-dead-owner-warm
    race are accepted, stated in the README, and must not silently widen.
