import { LemonButton } from 'lib/components/LemonButton'
import { IconRefresh } from 'lib/components/icons'

export function ErrorNetwork(): JSX.Element {
    return (
        <div>
            <h1 className="page-title">Network Error</h1>
            <p>There was an issue loading the requested resource.</p>
            <p>
                <LemonButton type="primary" onClick={() => window.location.reload()} icon={<IconRefresh />}>
                    Reload the page!
                </LemonButton>
            </p>
        </div>
    )
}
