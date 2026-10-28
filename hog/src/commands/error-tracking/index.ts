import { defineGroup } from '@/core/command'

import upload from './upload'

export default defineGroup({
    description: 'Upload symbols for readable stack traces in error tracking',
    aliases: ['et'],
    commands: { upload },
})
