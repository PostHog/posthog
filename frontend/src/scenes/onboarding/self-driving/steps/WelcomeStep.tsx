import selfDrivingHog from 'public/hedgehog/self-driving-hog.png'

import { RoughMark } from '../RoughMark'

/** The opener: what self-driving is, before we ask anyone to paste a command. */
export function WelcomeStep(): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center gap-5">
            <img src={selfDrivingHog} alt="A hedgehog riding in a self-driving car" className="w-full rounded-lg" />
            <div className="flex flex-col gap-2">
                {/* Highlight treatments mirror posthog.com's hero: blue mark on the headline
                    (Home/Test Headline, blue #2F80FA), amber rough-notation highlight in the body. */}
                <h1 className="text-2xl font-bold m-0">
                    Let's make your product{' '}
                    {/* A span, not <mark>: the app styles mark with an !important cream highlight. */}
                    <span
                        className="rounded-md px-1.5"
                        style={{ backgroundColor: 'rgba(47, 128, 250, 0.1)', color: '#2F80FA' }}
                    >
                        self-driving
                    </span>
                </h1>
                <p className="text-muted max-w-md mx-auto m-0">
                    PostHog runs on your product's context. One command gets it flowing, then agents can start{' '}
                    <RoughMark type="highlight" color="rgba(247, 165, 1, 0.15)" strokeWidth={1} multiline delay={400}>
                        finding and fixing things
                    </RoughMark>
                    , with you steering.
                </p>
            </div>
        </div>
    )
}
