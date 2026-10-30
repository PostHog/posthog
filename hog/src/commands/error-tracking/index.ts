import { defineGroup } from '@/core/command'

import inject from './inject'
import process from './process'
import upload from './upload'

export default defineGroup({
    description: 'Upload symbols for readable stack traces in error tracking',
    aliases: ['et'],
    commands: { inject, upload, process },
})
