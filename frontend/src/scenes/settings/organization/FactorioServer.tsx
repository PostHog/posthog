import { useValues } from 'kea'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { billingLogic } from 'scenes/billing/billingLogic'

import { BillingPlan } from '~/types'

function rot13(input: string): string {
    return input.replace(/[a-zA-Z0-9]/g, (char) => {
        const code = char.charCodeAt(0)
        if (char >= '0' && char <= '9') {
            return String.fromCharCode(((code - 48 + 5) % 10) + 48)
        }
        const base = char <= 'Z' ? 65 : 97
        return String.fromCharCode(((code - base + 13) % 26) + base)
    })
}

const OBFUSCATED_ADDRESS = '0.17.672.708:73155'
const OBFUSCATED_USERNAME = 'ratvarre'
const OBFUSCATED_PASSWORD = 'cebqhpgnhgbabzl'

export function FactorioServer(): JSX.Element | null {
    const { currentPlatformAddon } = useValues(billingLogic)

    if (currentPlatformAddon?.type !== BillingPlan.Boost) {
        return null
    }

    return (
        <div className="space-y-3 max-w-160">
            <p>
                As a thank-you for being a Boost customer, here are the credentials for the PostHog Factorio server.
                Build factories. Ship rockets. Don't tell engineering we're hosting this.
            </p>
            <div className="space-y-2">
                <div>
                    <label className="font-semibold">Server address</label>
                    <CodeSnippet compact thing="server address">
                        {rot13(OBFUSCATED_ADDRESS)}
                    </CodeSnippet>
                </div>
                <div>
                    <label className="font-semibold">Username</label>
                    <CodeSnippet compact thing="username">
                        {rot13(OBFUSCATED_USERNAME)}
                    </CodeSnippet>
                </div>
                <div>
                    <label className="font-semibold">Password</label>
                    <CodeSnippet compact thing="password">
                        {rot13(OBFUSCATED_PASSWORD)}
                    </CodeSnippet>
                </div>
            </div>
        </div>
    )
}
