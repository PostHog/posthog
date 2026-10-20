import { Spinner } from 'lib/lemon-ui/Spinner'

export function WelcomeLoading(): JSX.Element {
    return (
        <div className="flex min-h-60 items-center justify-center" role="status" aria-label="Loading">
            <Spinner className="text-2xl" />
        </div>
    )
}
