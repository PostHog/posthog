import * as BigQuery from '@google-cloud/bigquery'
import * as PubSub from '@google-cloud/pubsub'

type DummyCloud = {
    bigquery: typeof BigQuery
    pubsub: typeof PubSub
}

type DummyGoogle = {
    cloud: DummyCloud
}

export function createGoogle(): DummyGoogle {
    return {
        cloud: {
            bigquery: BigQuery,
            pubsub: PubSub,
        },
    }
}
