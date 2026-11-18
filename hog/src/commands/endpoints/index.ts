import { defineGroup } from '@/core/command'

import diff from './diff'
import get from './get'
import list from './list'
import open from './open'
import pull from './pull'
import push from './push'
import run from './run'

export default defineGroup({
    description: 'Manage PostHog endpoints as YAML files: pull, diff, push and run them',
    commands: { list, get, open, run, push, pull, diff },
})
