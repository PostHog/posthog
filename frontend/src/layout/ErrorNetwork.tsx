import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconRefresh } from 'lib/lemon-ui/icons'

export function ErrorNetwork(): JSX.Element {
    return (
        <div>
            <h1 className="mb-1 text-2xl font-bold">Network error</h1>
            <p>There was an issue loading the requested resource.</p>
            <p>
                <LemonButton type="primary" onClick={() => window.location.reload()} icon={<IconRefresh />}>
                    Reload the page!
                </LemonButton>
            </p>
        </div>
    )
}
