import { defineGroup } from '@/core/command'

import list from './list'
import remove from './remove'
import set from './set'

export default defineGroup({
    description: 'Manage the secrets a stack uses by name',
    commands: { set, list, remove },
})
