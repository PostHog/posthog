import { defineGroup } from '@/core/command'

import add from './add'

export default defineGroup({
    description: 'Add PostHog agent skills to this repository',
    commands: { add },
})
