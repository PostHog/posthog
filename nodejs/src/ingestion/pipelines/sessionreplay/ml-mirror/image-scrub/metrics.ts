import { Counter } from 'prom-client'

/** Observability for the image-scrub producer path, so "references produced but images never posted"
 *  (and fail-closed message drops) are alertable rather than invisible. */
export class ImageScrubMetrics {
    private static readonly imagesPosted = new Counter({
        name: 'session_replay_image_scrub_images_posted_total',
        help: 'Inlined images posted to the image-scrub topic (fresh, first sighting within the TTL)',
    })
    private static readonly imagesDeduped = new Counter({
        name: 'session_replay_image_scrub_images_deduped_total',
        help: 'Inlined images suppressed by dedup (a recent or in-batch duplicate)',
    })
    private static readonly emitFailures = new Counter({
        name: 'session_replay_image_scrub_emit_failures_total',
        help: 'Batched emits that failed (Redis/Kafka), dropping the whole ml-mirror message (fail-closed)',
    })
    private static readonly reservationRollbackFailures = new Counter({
        name: 'session_replay_image_scrub_reservation_rollback_failures_total',
        help: 'Dedup reservations that could not be rolled back after a failed produce (stay set until TTL)',
    })

    public static observeEmit(posted: number, deduped: number): void {
        if (posted > 0) {
            this.imagesPosted.inc(posted)
        }
        if (deduped > 0) {
            this.imagesDeduped.inc(deduped)
        }
    }

    public static incrementEmitFailure(): void {
        this.emitFailures.inc()
    }

    public static incrementReservationRollbackFailure(): void {
        this.reservationRollbackFailures.inc()
    }
}
