import * as pubsub from '@google-cloud/pubsub'
import * as gcs from '@google-cloud/storage'
import * as scaffold from '@posthog/plugin-scaffold'
import * as AWS from 'aws-sdk'
import crypto from 'crypto'
import * as genericPool from 'generic-pool'
import { PassThrough } from 'stream'
import * as url from 'url'

import { defaultConfig } from '~/src/config/config'
import { trackedFetch } from '~/src/utils/fetch'

import { isTestEnv } from '../../utils/env-utils'
import { HttpCallRecorder, recordedFetch } from '../../utils/recorded-fetch'
import { writeToFile } from './extensions/test-utils'

export const globalHttpCallRecorder = new HttpCallRecorder()
const shouldRecordHttpCalls =
    defaultConfig.DESTINATION_MIGRATION_DIFFING_ENABLED === true && defaultConfig.TASKS_PER_WORKER === 1
// Always use recordedFetch as its only a wrapper around trackedFetch
export const conditionalTrackedFetch = (url: any, init?: any) => {
    if (shouldRecordHttpCalls) {
        return recordedFetch(globalHttpCallRecorder, url, init)
    }
    return trackedFetch(url, init)
}

export const AVAILABLE_IMPORTS = {
    ...(isTestEnv()
        ? {
              'test-utils/write-to-file': writeToFile,
          }
        : {}),
    '@google-cloud/pubsub': pubsub,
    '@google-cloud/storage': gcs,
    '@posthog/plugin-scaffold': scaffold,
    'aws-sdk': AWS,
    'generic-pool': genericPool,
    'node-fetch': conditionalTrackedFetch,
    crypto: crypto,
    stream: { PassThrough },
    url: url,
}

// Export the recorder to make it accessible for inspection
export function getHttpCallRecorder(): HttpCallRecorder {
    return globalHttpCallRecorder
}
