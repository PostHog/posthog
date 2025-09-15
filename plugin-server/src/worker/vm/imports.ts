import * as pubsub from '@google-cloud/pubsub'
import * as gcs from '@google-cloud/storage'
import * as AWS from 'aws-sdk'
import crypto from 'crypto'
import * as genericPool from 'generic-pool'
import { PassThrough } from 'stream'
import * as url from 'url'

import * as scaffold from '@posthog/plugin-scaffold'

import { isTestEnv } from '../../utils/env-utils'
import { legacyFetch } from '../../utils/request'
import { writeToFile } from './extensions/test-utils'

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
    'node-fetch': legacyFetch,
    crypto: crypto,
    stream: { PassThrough },
    url: url,
}
