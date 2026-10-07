import { LATEST_BATCH_LOOKBACK_DAYS } from './autoresearchPipelineLogic'

export type PredictionsPeopleView = 'most_likely' | 'biggest_movers' | 'least_likely'

export const PREDICTIONS_PEOPLE_VIEWS: { value: PredictionsPeopleView; label: string }[] = [
    { value: 'most_likely', label: 'Most likely' },
    { value: 'biggest_movers', label: 'Biggest movers' },
    { value: 'least_likely', label: 'Least likely' },
]

export const PREDICTIONS_PEOPLE_LIMIT = 50

const ORDER_BY: Record<PredictionsPeopleView, string> = {
    most_likely: 'p_latest DESC',
    biggest_movers: 'abs(change) DESC, p_latest DESC',
    least_likely: 'p_latest ASC',
}

/**
 * HogQL for the top people of the latest prediction batch, with the `{pipeline_id}` placeholder.
 * The query picks the top person ids first and reads display names for only those ids,
 * so the persons read never grows with the batch size.
 */
export function predictionsPeopleQuery(view: PredictionsPeopleView): string {
    return `
        -- Capture can shift the timestamps of one batch apart, so the latest batch is its prediction date.
        WITH latest AS (
            SELECT max(properties.$autoresearch_prediction_date) AS prediction_date
            FROM events
            WHERE event = 'autoresearch_prediction'
              AND properties.$autoresearch_pipeline_id = {pipeline_id}
              AND timestamp >= now() - INTERVAL ${LATEST_BATCH_LOOKBACK_DAYS} DAY
        ),
        scored AS (
            SELECT
                coalesce(nullIf(properties.$autoresearch_person_id, ''), distinct_id) AS person_id,
                properties.$autoresearch_prediction_date = (SELECT prediction_date FROM latest) AS in_latest,
                toFloat(properties.$autoresearch_p_y) AS p,
                timestamp
            FROM events
            WHERE event = 'autoresearch_prediction'
              AND properties.$autoresearch_pipeline_id = {pipeline_id}
              AND timestamp >= now() - INTERVAL ${LATEST_BATCH_LOOKBACK_DAYS} DAY
        ),
        top AS (
            SELECT
                person_id,
                argMaxIf(p, timestamp, in_latest) AS p_latest,
                -- A person with one score has no previous score, so their change is 0.
                if(countIf(not in_latest) > 0, p_latest - argMaxIf(p, timestamp, not in_latest), 0) AS change,
                maxIf(timestamp, in_latest) AS last_scored
            FROM scored
            GROUP BY person_id
            HAVING countIf(in_latest) > 0
            ORDER BY ${ORDER_BY[view]}
            LIMIT ${PREDICTIONS_PEOPLE_LIMIT}
        ),
        names AS (
            SELECT
                toString(id) AS person_id,
                argMax(coalesce(
                    nullIf(toString(properties.email), ''),
                    nullIf(toString(properties.name), '')
                ), version) AS display_name
            FROM raw_persons
            WHERE id IN (SELECT toUUID(person_id) FROM top)
            GROUP BY id
            HAVING argMax(is_deleted, version) = 0
        )
        -- Join on the person UUID: the implicit person join goes via distinct_id,
        -- which drops scored people whose prediction events are not person-mapped.
        SELECT
            tuple(t.person_id, n.display_name) AS person,
            round(100 * t.p_latest, 1) AS probability,
            round(100 * t.change, 1) AS change,
            t.last_scored AS last_scored
        FROM top t
        LEFT JOIN names n ON n.person_id = t.person_id
        ORDER BY ${ORDER_BY[view]}
    `
}
