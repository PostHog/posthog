import { defineGroup } from '@/core/command'

import login from './login'
import logout from './logout'
import status from './status'

export default defineGroup({
    description: 'Log in to PostHog, log out, and check who hog is logged in as',
    commands: { login, logout, status },
})
