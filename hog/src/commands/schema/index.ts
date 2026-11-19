import { defineGroup } from '@/core/command'

import pull from './pull'
import status from './status'

export default defineGroup({
    description: 'Generate a typed PostHog SDK from your event definitions',
    commands: { pull, status },
})
