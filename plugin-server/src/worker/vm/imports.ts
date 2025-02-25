import * as pubsub from '@google-cloud/pubsub'
import * as gcs from '@google-cloud/storage'
import * as scaffold from '@posthog/plugin-scaffold'
import * as AWS from 'aws-sdk'
import crypto from 'crypto'
import * as genericPool from 'generic-pool'
import { PassThrough } from 'stream'
import * as url from 'url'

import { defaultConfig } from '../../config/config'
import { isTestEnv } from '../../utils/env-utils'
import { trackedFetch } from '../../utils/fetch'
import { HttpCallRecorder, recordedFetch } from '../../utils/recorded-fetch'
import { writeToFile } from './extensions/test-utils'

// Create a global recorder instance
export const globalHttpCallRecorder = new HttpCallRecorder()

// Create a function that uses the global recorder
export const recordedTrackedFetch = (url: any, init?: any) => recordedFetch(globalHttpCallRecorder, url, init)

// Create a function that conditionally uses the global recorder based on config
export const conditionalRecordedTrackedFetch = (url: any, init?: any) => {
    // Only use HTTP call recording if destination diffing is enabled and tasks_per_worker is 10
    const shouldRecordHttpCalls =
        defaultConfig.DESTINATION_MIGRATION_DIFFING_ENABLED === true && defaultConfig.TASKS_PER_WORKER === 10

    return shouldRecordHttpCalls ? recordedFetch(globalHttpCallRecorder, url, init) : trackedFetch(url, init)
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
    'node-fetch': recordedTrackedFetch, // Use our recorded fetch wrapper
    crypto: crypto,
    stream: { PassThrough },
    url: url,
}

// Export the recorder to make it accessible for inspection
export function getHttpCallRecorder(): HttpCallRecorder {
    return globalHttpCallRecorder
}
