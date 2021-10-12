import * as bigquery from '@google-cloud/bigquery'
import * as pubsub from '@google-cloud/pubsub'
import * as gcs from '@google-cloud/storage'
import * as contrib from '@posthog/plugin-contrib'
import * as scaffold from '@posthog/plugin-scaffold'
import * as AWS from 'aws-sdk'
import crypto from 'crypto'
import * as faker from 'faker'
import * as genericPool from 'generic-pool'
import * as jsonwebtoken from 'jsonwebtoken'
import fetch from 'node-fetch'
import * as pg from 'pg'
import snowflake from 'snowflake-sdk'
import { PassThrough } from 'stream'
import * as url from 'url'
import * as zlib from 'zlib'

import { writeToFile } from './extensions/test-utils'

export const imports = {
    ...(process.env.NODE_ENV === 'test'
        ? {
              'test-utils/write-to-file': writeToFile,
          }
        : {}),
    '@google-cloud/bigquery': bigquery,
    '@google-cloud/pubsub': pubsub,
    '@google-cloud/storage': gcs,
    '@posthog/plugin-contrib': contrib,
    '@posthog/plugin-scaffold': scaffold,
    'aws-sdk': AWS,
    'generic-pool': genericPool,
    'node-fetch': fetch,
    'snowflake-sdk': snowflake,
    crypto: crypto,
    jsonwebtoken: jsonwebtoken,
    faker: faker,
    pg: pg,
    stream: { PassThrough },
    url: url,
    zlib: zlib,
}
