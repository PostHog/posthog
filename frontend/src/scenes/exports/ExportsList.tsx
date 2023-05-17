import { useValues } from 'kea'
import { useEffect, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from '../teamLogic'
import assert from 'assert'

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
                        <tr key={export_.export_id}>
                            <td>{export_.name}</td>
                            <td>{export_.destination.type}</td>
                            <td>{export_.schedule.interval}</td>
                            <td>{export_.status}</td>
                            <td>{export_.last_run}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            {/* If we are loading, we overlay a spinner */}
            {loading && <div>Loading...</div>}
        </>
    )
}

const useCurrentTeamId = (): { currentTeamId: number } => {
    // Returns the current team ID from the team logic. We assume that in all
    // contexts we will have a current team ID, and assert that here such that
    // we can ensure the return value type and avoid having to check for
    // undefined in the caller.
    const { currentTeamId } = useValues(teamLogic)
    assert(currentTeamId !== undefined, 'currentTeamId should not be undefined')
    return { currentTeamId }
}

type UseExportsReturnType = {
    loading: boolean
    error?: Error
    exports?: BatchExport[]
}

const useExports = (teamId: number): UseExportsReturnType => {
    // Returns a list of exports for the given team. While we are fetching the
    // list, we return a loading: true as part of the state. On component
    // unmount we ensure that we clean up the fetch request by use of the
    // AbortController.
    //
    // If we get an error, we return this to the caller.
    const [state, setExports] = useState<UseExportsReturnType>({
        loading: true,
        exports: undefined,
        error: undefined,
    })

    // Make the actual fetch request as a side effect.
    useEffect(() => {
        const controller = new AbortController()
        const signal = controller.signal

        fetch(`/api/projects/${teamId}/exports/`, { signal })
            .then((response) => response.json() as Promise<BatchExportsResponse>)
            .then((data) => {
                setExports({ loading: false, exports: data.exports, error: undefined })
            })
            .catch((error) => {
                setExports({ loading: false, exports: undefined, error })
            })

        return () => controller.abort()
    }, [teamId])

    return state
}

type S3Destination = {
    // At the moment we just support S3, but we include this nesting to
    // allow for future expansion easily without needing to change the
    // interface.
    type: 'S3'
    config: {
        bucket: string
        prefix: string
        aws_access_key_id: string
        aws_secret_access_key: string
    }
}

type IntervalSchedule = {
    // At the moment we just support interval based exports. It's possible
    // that we might want to extend this however to other types of schedules
    // to support more complex use cases. This structure allows us to do
    // that without needing to change the interface.
    type: 'INTERVAL'
    interval: 'HOURLY' | 'DAILY' | 'WEEKLY' | 'MONTHLY'
}

type BatchExport = {
    export_id: number
    team_id: number
    name: string
    destination: S3Destination
    schedule: IntervalSchedule
    status: 'RUNNING' | 'FAILED' | 'COMPLETED' | 'PAUSED'
    created_at: string
    last_updated_at: string
}

export type BatchExportsResponse = {
    exports: BatchExport[]
}
