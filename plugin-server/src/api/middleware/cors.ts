import cors from 'cors'

/**
 * Custom origin validation function that allows *.posthog.com domains
 * without using wildcards for better security
 */
function isPostHogDomain(origin: string): boolean {
    // Allow localhost for development
    if (origin.includes('localhost')) {
        return true
    }

    // Check if the origin ends with .posthog.com
    return origin.endsWith('.posthog.com')
}

/**
 * CORS configuration that allows *.posthog.com domains
 */
export const corsMiddleware = cors({
    origin: (origin: string | undefined, callback) => {
        // Allow requests with no origin (like mobile apps or curl requests)
        if (!origin) {
            return callback(null, true)
        }

        if (isPostHogDomain(origin)) {
            return callback(null, true)
        }

        // Reject other origins
        return callback(new Error('Not allowed by CORS'))
    },
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allowedHeaders: [
        'Origin',
        'X-Requested-With',
        'Content-Type',
        'Accept',
        'Authorization',
        'X-PostHog-Token',
        'X-Requested-With',
        'Cache-Control',
        'Pragma',
    ],
})
