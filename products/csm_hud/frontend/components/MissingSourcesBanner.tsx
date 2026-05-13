import { useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { csmHudSceneLogic } from '../logics/csmHudSceneLogic'
import { MissingSourceKind, newSourceKind, sourceDescription, sourceLabel } from '../utils/missingSources'

function returnToFleetUrl(): string {
    return urls.csmHudFleet()
}

function actionForSource(source: MissingSourceKind): JSX.Element | null {
    const kind = newSourceKind(source)
    if (!kind) {
        return null
    }
    return (
        <LemonButton
            type="secondary"
            size="small"
            to={urls.dataWarehouseSourceNew(kind, returnToFleetUrl(), 'CSM HUD')}
        >
            Connect {sourceLabel(source)}
        </LemonButton>
    )
}

export function MissingSourcesBanner(): JSX.Element | null {
    const { missingSources } = useValues(csmHudSceneLogic)
    if (missingSources.length === 0) {
        return null
    }
    return (
        <LemonBanner type="info">
            <div className="space-y-2">
                <div className="font-medium">Some data isn't available on this team</div>
                <ul className="space-y-2 list-disc pl-5">
                    {missingSources.map((source) => (
                        <li key={source}>
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <span className="font-medium">{sourceLabel(source)}</span>{' '}
                                    <span className="text-muted">— {sourceDescription(source)}</span>
                                </div>
                                {actionForSource(source)}
                            </div>
                        </li>
                    ))}
                </ul>
            </div>
        </LemonBanner>
    )
}
