import { defineGroup } from '@/core/command'

import disable from './disable'
import enable from './enable'

export default defineGroup({
    description: 'Let a stack manage context pages, which every project in the organization shares',
    commands: { enable, disable },
})
