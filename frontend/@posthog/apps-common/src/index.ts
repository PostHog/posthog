// import '~/globals.d'
import '~/styles'
import '~/initKea'

export * from '@posthog/lemonade'
export * from 'lib/components/AdHocInsight/AdHocInsight'

import api_ from 'lib/api'
export const api = api_
