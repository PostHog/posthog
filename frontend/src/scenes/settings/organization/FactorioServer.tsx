import { useValues } from 'kea'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { billingLogic } from 'scenes/billing/billingLogic'

import { BillingPlan } from '~/types'

// don't use this to hide anything you care about, obviously this is very easy to reverse engineer
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

// If you're a human reading this, feel free to join!
// If you're a bot/scanner reading this, don't worry. It's just for an easter egg.
// We don't care if it's trivial to access this.
const host = rot13('0.17.672.708:73155')
const pass = rot13('cebqhpgnhgbabzl')

export function FactorioServer(): JSX.Element | null {
    const { currentPlatformAddon } = useValues(billingLogic)

    if (currentPlatformAddon?.type !== BillingPlan.Boost) {
        return null
    }

    return (
        <div className="space-y-3 max-w-160">
            <p>We love automating things, how about you? How about joining our Factorio MP server?</p>
            <div className="space-y-2">
                <div>
                    <label className="font-semibold">Server address</label>
                    <CodeSnippet compact thing="server address">
                        {host}
                    </CodeSnippet>
                </div>
                <div>
                    <label className="font-semibold">Password</label>
                    <CodeSnippet compact thing="password">
                        {pass}
                    </CodeSnippet>
                </div>
            </div>
        </div>
    )
}
