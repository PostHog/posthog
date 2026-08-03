import selfDrivingHog from 'public/hedgehog/self-driving-hog.png'

/** The opener: what self-driving is, before we ask anyone to paste a command. */
export function WelcomeStep(): JSX.Element {
    return (
        <div className="flex flex-col items-center text-center gap-5">
            <img src={selfDrivingHog} alt="A hedgehog riding in a self-driving car" className="w-full rounded-lg" />
            <div className="flex flex-col gap-2">
                <h1 className="text-2xl font-bold m-0">Let's make your product self-driving</h1>
                <p className="text-muted max-w-md mx-auto m-0">
                    PostHog runs on your product's context. One command gets it flowing, then agents can start finding
                    and fixing things, with you steering.
                </p>
            </div>
        </div>
    )
}
