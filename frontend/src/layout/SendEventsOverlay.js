import React, { useEffect, useRef, useState } from 'react'
import { router } from 'kea-router'
import { useValues } from 'kea'
import { JSSnippet } from 'lib/components/JSSnippet'

export function SendEventsOverlay({ image, user }) {
    const overlay = useRef()
    const imageRef = useRef()
    const [animate, setAnimate] = useState(false)
    const { location } = useValues(router)

    useEffect(() => {
        setTimeout(() => setAnimate(true), 1000)
    }, [])

    useEffect(() => {
        setAnimate(false)
    }, [location])

    return (
        <div ref={overlay} className={'send-events-overlay ' + (animate && 'animate')}>
            <img
                ref={imageRef}
                src={`${image}?${Date.now()}`}
                style={{ opacity: animate ? 1 : 0 }}
                className="overlay-image"
                onLoad={() => setAnimate(true)}
            />
            <div className="overlay">
                <div className="overlay-inner">
                    <h2>Start sending events to PostHog</h2>
                    <div style={{ width: 600 }}>
                        To get started using PostHog, you'll need to send us some events. By copying the snippet below
                        into the header, you can be up and running in minutes! You can put this snippet on any domain,
                        and it'll capture users across.
                    </div>
                    <JSSnippet user={user} />
                    <a href="https://posthog.com/docs/integrations">Using Python/Ruby/Node/Go/PHP instead?</a>
                    <br />
                    <br />
                    {window.location.href.indexOf('127.0.0.1') > -1 && (
                        <div>
                            <h3>Running locally?</h3>
                            It's hard to send events to PostHog running locally. If you want to have a play,{' '}
                            <a href="/demo" target="_blank">
                                click here for our 'HogFlix' demo environment
                            </a>
                            .<br />
                            <br />
                            Once you're ready, you can deploy it to a live environment.
                            <br />
                            <br />
                            <a href="https://heroku.com/deploy?template=https://github.com/posthog/posthog">
                                <img src="https://www.herokucdn.com/deploy/button.svg" />
                            </a>
                            <br />
                            <br />
                            <a href="https://github.com/PostHog/posthog">Click here</a> for instructions on deploying
                            with Docker or from source.
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
