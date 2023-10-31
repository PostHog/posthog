import * as BigQuery from '@google-cloud/bigquery'
import * as PubSub from '@google-cloud/pubsub'

type MockedCloud = {
    bigquery: typeof BigQuery
    pubsub: typeof PubSub
}

type MockedGoogle = {
    cloud: MockedCloud
}

export function createGoogle(): MockedGoogle {
    return {
        cloud: {
            bigquery: BigQuery,
            pubsub: PubSub,
        },
    }
}
