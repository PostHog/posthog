import { defineGroup } from '@/core/command'

import setup from './setup'

export default defineGroup({
    description: 'Let CI jobs use hog with their OIDC token instead of a stored key',
    commands: { setup },
})
