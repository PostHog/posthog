import React, { useEffect } from 'react'

export function Papercups(): JSX.Element {
    useEffect(() => {
        window.Papercups = {
            config: {
                accountId: '873f5102-d267-4b09-9de0-d6e741e0e076',
                title: 'Welcome to PostHog',
                subtitle: 'Ask us anything in the chat window below 😊',
                primaryColor: '#5375ff',
                greeting: "Hi! Send us a message and we'll respond as soon as we can.",
                customer: {
                    email: '{{ request.user.email }}',
                    name: '{{ request.user.first_name }}',
                },
                newMessagePlaceholder: 'Start typing…',
                baseUrl: 'https://app.papercups.io',
            },
        }

        const script = document.createElement('script')

        script.src = 'https://app.papercups.io/widget.js'
        script.async = true
        script.defer = true

        document.body.appendChild(script)

        return () => {
            document.body.removeChild(script)
            window.Papercups = undefined
        }
    }, [])

    return <></>
}
