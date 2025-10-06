'use client'

import './globals.css'

import { AuthProvider } from '@/lib/auth'
import { initPostHog } from '@/lib/posthog'
import { useEffect } from 'react'

export default function RootLayout({ children }: { children: React.ReactNode }): React.JSX.Element {
    useEffect(() => {
        initPostHog()
    }, [])

    return (
        <html lang="en" data-theme="hedgebox">
            <body>
                <AuthProvider>
                    <div className="min-h-screen bg-base-100">{children}</div>
                </AuthProvider>
            </body>
        </html>
    )
}
