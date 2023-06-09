import { SceneExport } from 'scenes/sceneTypes'
import { urls } from '../urls'
import { Link } from '../../lib/lemon-ui/Link'
import { useCurrentTeamId, useExports } from './api'
import { LemonButton } from '../../lib/lemon-ui/LemonButton'

export const scene: SceneExport = {
    component: Exports,
}

export function Exports(): JSX.Element {
    // Displays a list of exports for the current project. We use the
    // useCurrentTeamId hook to get the current team ID, and then use the
    // useExports hook to fetch the list of exports for that team.
    const { currentTeamId } = useCurrentTeamId()
    const { loading, exports, error } = useExports(currentTeamId)

    // If exports hasn't been set yet, we display a placeholder and a loading
    // spinner.
    if (exports === undefined) {
        return (
            <div>
                <h1>Exports</h1>
                <p>Fetching exports...</p>
            </div>
        )
    }

    // If we have an error, we display the error message.
    if (error) {
        return (
            <div>
                <h1>Exports</h1>
                <p>Error fetching exports: {error}</p>
            </div>
        )
    }

    // If we have exports we display them in a table, showing:
    // - The export type e.g. S3, Snowflake, etc.
    // - The export frequency e.g. hourly, daily, etc.
    // - The export status e.g. running, failed, etc.
    // - The export last run time.
    return (
        <>
            <h1>Exports</h1>
            <table>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Type</th>
                        <th>Frequency</th>
                        <th>Status</th>
                        <th>Last run</th>
                    </tr>
                </thead>
                <tbody>
                    {exports.map((export_) => (
                        <tr key={export_.id}>
                            <td>
                                <Link to={urls.viewExport(export_.id)}>{export_.name}</Link>
                            </td>
                            <td>{export_.destination.type}</td>
                            <td>{export_.interval}</td>
                            <td>{export_.status}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <LemonButton to={urls.createExport()}>Create export</LemonButton>
            {/* If we are loading, we overlay a spinner */}
            {loading && <div>Loading...</div>}
        </>
    )
}
