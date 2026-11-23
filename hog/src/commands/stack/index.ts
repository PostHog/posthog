import { defineGroup } from '@/core/command'

import adopt from './adopt'
import check from './check'
import contextPages from './context-pages'
import diff from './diff'
import generate from './generate'
import init from './init'
import pull from './pull'
import push from './push'
import reconcile from './reconcile'
import secret from './secret'

export default defineGroup({
    description: 'Manage PostHog in code: definitions in a stack folder that PostHog creates and keeps in step',
    commands: { check, diff, push, pull, init, generate, adopt, reconcile, secret, 'context-pages': contextPages },
})
