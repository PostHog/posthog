import { defineGroup } from '@/core/command'

import add from './add'
import login from './login'
import logout from './logout'
import migrate from './migrate'
import status from './status'

export default defineGroup({
    description: 'Log in to PostHog, add scopes, log out, and check who hog is logged in as',
    commands: { login, add, logout, migrate, status },
})
