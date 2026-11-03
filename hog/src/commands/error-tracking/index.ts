import { defineGroup } from '@/core/command'

import clone from './clone'
import download from './download'
import extract from './extract'
import inject from './inject'
import process from './process'
import release from './release'
import upload from './upload'

export default defineGroup({
    description: 'Upload symbols for readable stack traces in error tracking',
    aliases: ['et'],
    commands: { inject, clone, upload, process, release, download, extract },
})
