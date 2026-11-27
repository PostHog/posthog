'use client'

import { useState, type FormEvent } from 'react'

export default function SignupPage() {
    const [status, setStatus] = useState<'idle' | 'done' | 'failed'>('idle')

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        const email = new FormData(event.currentTarget).get('email')
        const response = await fetch('/api/signup', { method: 'POST', body: JSON.stringify({ email }) })
        setStatus(response.ok ? 'done' : 'failed')
    }

    return (
        <form onSubmit={submit}>
            <label>
                Email <input name="email" type="email" required />
            </label>
            <button type="submit">Create account</button>
            {status === 'done' && <p>Welcome to Hedge Goods.</p>}
            {status === 'failed' && <p>We couldn't create your account.</p>}
        </form>
    )
}
