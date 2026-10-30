export type AuthNotes = readonly string[]

/**
 * The typed notes in the top-left corner of every `AuthScene`, by screen and then by state.
 * `AuthScene` adds the `// ` prefix. Keep each line short, because the notes do not wrap.
 */
export const AUTH_NOTES = {
    auth: {
        firstVisit: ['hey, good to see you', '500,000+ teams ship here'],
        welcomeBack: ['welcome back', '500,000+ teams ship here'],
        createAccount: ['create an account', '1M events free, every month'],
        signupProfile: ['almost there', 'last step'],
    },
    login2fa: {
        default: ['one more step', "checking it's really you"],
    },
    verifyEmail: {
        pending: ['one email away', 'we just hit send'],
        sendFailed: ['the email did not go', 'give it another send'],
        success: ['verified', 'go explore'],
        invalid: ['nothing to verify', "let's start again"],
    },
    inviteSignup: {
        invited: (organizationName: string): AuthNotes => [
            "you've been invited",
            `${organizationName.toLowerCase()} is waiting`,
        ],
        existingUser: ['hey, welcome back', 'one more org for you'],
        invalid: ['hmm', "this invite isn't right"],
    },
    passwordReset: {
        request: ['it happens', 'to the best of us'],
        sent: ['check your inbox', 'a reset link is on its way'],
        throttled: ['easy there', 'too many tries, wait a bit'],
        emailUnavailable: ['no email on this instance', 'your admin can help'],
    },
    passwordResetComplete: {
        newPassword: ['almost there', 'one new password away'],
        invalid: ['this link stopped working', 'request a fresh one'],
    },
    twoFactorReset: {
        reset: ['locked out?', "let's fix that"],
        done: ['2fa reset', 'back in you go'],
        invalid: ['this link stopped working', 'ask for a new one'],
    },
    cliAuthorize: {
        authorize: ['hello, terminal', 'only grant what you need'],
        authorized: ['authorized', 'your terminal has a key now'],
    },
    cliLive: {
        default: ['posthog live', 'events, in your terminal'],
        authorized: ['posthog live', 'events are on their way'],
        error: ['posthog live', 'try again from your terminal'],
    },
    vercelConnect: {
        pick: ['vercel, meet posthog', 'pick an organization'],
        linked: ['vercel, meet posthog', "you're linked up"],
        error: ['vercel, meet posthog', "that didn't go to plan"],
    },
    accountMismatch: {
        default: ['two accounts', 'one browser'],
    },
    accountConnected: {
        connected: ['all connected', 'back to work'],
        pending: ['almost connected', 'waiting on an admin'],
        failed: ["that didn't connect", 'give it another go'],
        invalid: ['nothing to connect', 'this link went nowhere'],
    },
    credentialReview: {
        default: ['welcome to posthog', 'quick security check'],
    },
    confirmOrganization: {
        default: ['almost there', 'name your organization'],
    },
    unsubscribe: {
        loading: ['one moment', 'tidying your inbox'],
        done: ['inbox zero', 'one email lighter'],
        failed: ['hmm', "that link didn't work"],
    },
    desktopBridge: {
        default: ['posthog desktop', 'opening the app'],
    },
    preflight: {
        default: ['self-hosting posthog', 'checking the plumbing'],
    },
    exporter: {
        default: ['someone shared this with you', 'unlock to take a look'],
    },
} as const satisfies Record<string, Record<string, AuthNotes | ((...args: string[]) => AuthNotes)>>
