/*
For better code readability, this file contains the components we show on the 
left side (or bottom on mobile) in the signup page, as we distinguish between
cloud and self-hosted.
*/

import React from 'react'
import { CheckOutlined, CloudFilled, GithubFilled } from '@ant-design/icons'

// PostHog Cloud
export function SignupSideContentCloud({ utm_tags }: { utm_tags: string }): JSX.Element {
    return (
        <>
            <h1 className="page-title">Try PostHog Cloud!</h1>
            <div className="showcase-description">
                PostHog Cloud is the hosted version of our open source package.
                <br />
                <br />
                We manage hosting, scaling and upgrades.
                <div className="signup-list">
                    <div>
                        <CheckOutlined /> First 10k events free every month
                    </div>
                    <div>
                        <CheckOutlined /> Pay per use, cancel anytime
                    </div>
                    <div>
                        <CheckOutlined /> Community, Slack &amp; email support
                    </div>
                </div>
                <div className="alt-options">
                    <h3>Interested in self-hosting?</h3>
                    <a
                        href={`https://posthog.com/pricing?o=vpc&${utm_tags}`}
                        target="_blank"
                        rel="noopener"
                        className="alt-option"
                    >
                        <div>
                            <CloudFilled />
                        </div>
                        <div>
                            <b>Private cloud</b>
                            <div>Managed deployments, maximum scalability</div>
                        </div>
                    </a>
                    <a
                        href={`https://posthog.com/docs/deployment?${utm_tags}`}
                        target="_blank"
                        rel="noopener"
                        className="alt-option"
                    >
                        <div>
                            <GithubFilled />
                        </div>
                        <div>
                            <b>Open source</b>
                            <div>Deploy on your own infrastructure. Free forever.</div>
                        </div>
                    </a>
                </div>
            </div>
        </>
    )
}

// PostHog VPC or self-hosted (OSS)
export function SignupSideContentHosted({ utm_tags }: { utm_tags: string }): JSX.Element {
    return (
        <>
            <h1 className="page-title">Try PostHog now!</h1>
            <div className="showcase-description">
                PostHog is an open source full product analytics suite.
                <div className="signup-list">
                    <div>
                        <CheckOutlined /> Fully featured product
                    </div>
                    <div>
                        <CheckOutlined /> Unlimited events
                    </div>
                    <div>
                        <CheckOutlined /> Data in your own infrastructure
                    </div>
                </div>
                <div className="alt-options">
                    <h3>Interested in a hosted solution?</h3>
                    <a
                        href={`https://posthog.com/pricing?o=cloud&${utm_tags}`}
                        target="_blank"
                        rel="noopener"
                        className="alt-option"
                        style={{ border: 0 }}
                    >
                        <div>
                            <CloudFilled />
                        </div>
                        <div>
                            <b>PostHog cloud</b>
                            <div>Fully hosted version, no maintenance headaches</div>
                        </div>
                    </a>
                </div>
            </div>
        </>
    )
}
