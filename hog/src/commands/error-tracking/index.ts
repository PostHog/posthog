import { defineGroup } from '@/core/command'

import clone from './clone'
import inject from './inject'
import process from './process'
import upload from './upload'

export default defineGroup({
    description: 'Upload symbols for readable stack traces in error tracking',
    aliases: ['et'],
    commands: { inject, clone, upload, process },
})
