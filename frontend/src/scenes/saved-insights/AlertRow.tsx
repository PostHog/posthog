import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { AlertType } from 'products/alerts/frontend/types'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'

export function AlertRow({ alert }: { alert: AlertType }): JSX.Element {
    return (
        <ProjectHomePageCompactListItem
            title={alert.name}
            subtitle={
                alert.last_checked_at ? (
                    <div className="flex items-center gap-1">
                        {alert.last_value !== undefined && (
                            <>
                                <span className="font-medium">Value: {alert.last_value}</span>
                                <span>•</span>
                            </>
                        )}
                        <span>
                            Last checked <TZLabel time={alert.last_checked_at} />
                        </span>
                    </div>
                ) : (
                    'Not yet checked'
                )
            }
            to={urls.alert(alert.id)}
            dataAttr="firing-alert-item"
        />
    )
}
