import { useValues } from 'kea'
import { teamLogic } from '../teamLogic'
import { useCallback, useEffect, useState } from 'react'
import api from '../../lib/api'

export const useCurrentTeamId = (): { currentTeamId: number } => {
    // Returns the current team ID from the team logic. We assume that in all
    // contexts we will have a current team ID, and assert that here such that
    // we can ensure the return value type and avoid having to check for
    // undefined in the caller.
    const { currentTeamId } = useValues(teamLogic)

    if (currentTeamId == null) {
        throw Error('currentTeamId should not be undefined')
    }

    return { currentTeamId }
}

type UseExportsReturnType = {
    loading: boolean
    error?: Error
    exports?: BatchExport[]
}

export const useExports = (teamId: number): UseExportsReturnType => {
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

        fetch(`/api/projects/${teamId}/batch_exports/`, { signal })
            .then((response) => response.json() as Promise<BatchExportsResponse>)
            .then((data) => {
                setExports({ loading: false, exports: data.results, error: undefined })
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
        bucket_name: string
        region: string
        key_template: string
        aws_access_key_id: string
        aws_secret_access_key: string
    }
}

type Destination = S3Destination

export type BatchExportData = {
    // User provided data for the export. This is the data that the user
    // provides when creating the export.
    name: string
    destination: Destination
    interval: 'hour' | 'day'
}

export type BatchExport = {
    id: string
    team_id: number
    status: 'RUNNING' | 'FAILED' | 'COMPLETED' | 'PAUSED'
    created_at: string
    last_updated_at: string
} & BatchExportData

export type BatchExportsResponse = {
    results: BatchExport[]
}

export const useCreateExport = (): {
    loading: boolean
    error: Error | null
    createExport: (teamId: number, exportData: BatchExportData) => Promise<void>
} => {
    // Return a callback that can be used to create an export. We also include
    // the loading state and error.
    const [state, setState] = useState<{ loading: boolean; error: Error | null }>({ loading: false, error: null })

    const createExport = useCallback((teamId: number, exportData: BatchExportData) => {
        setState({ loading: true, error: null })
        return api.createResponse(`/api/projects/${teamId}/batch_exports/`, exportData).then((response) => {
            if (response.ok) {
                setState({ loading: false, error: null })
            } else {
                // TODO: parse the error response.
                const error = new Error(response.statusText)
                setState({ loading: false, error: error })
                throw error
            }
        })
    }, [])

    return { createExport, ...state }
}

export const useExport = (
    teamId: number,
    exportId: string
): { loading: boolean; export_: BatchExport | undefined; error: Error | undefined } => {
    // Fetches the export details for the given team and export ID.
    const [loading, setLoading] = useState(true)
    const [export_, setExport] = useState<BatchExport>()
    const [error, setError] = useState<Error>()

    useEffect(() => {
        const controller = new AbortController()
        const signal = controller.signal

        setLoading(true)
        setError(undefined)

        fetch(`/api/projects/${teamId}/batch_exports/${exportId}`, { signal })
            .then((res) => res.json())
            .then((data) => {
                setExport(data)
                setLoading(false)
            })
            .catch((error) => {
                setError(error)
                setLoading(false)
            })

        return () => controller.abort()
    }, [teamId, exportId])

    return { loading, export_, error }
}

export const useExportRuns = (
    teamId: number,
    exportId: string
): { loading: boolean; exportRuns: BatchExportRun[] | undefined; error: Error | undefined } => {
    // Fetches the export runs for the given team and export ID.
    const [loading, setLoading] = useState(true)
    const [exportRuns, setExportRuns] = useState<BatchExportRun[]>()
    const [error, setError] = useState<Error>()

    useEffect(() => {
        const controller = new AbortController()
        const signal = controller.signal

        setLoading(true)
        setError(undefined)

        fetch(`/api/projects/${teamId}/batch_exports/${exportId}/runs`, { signal })
            .then((res) => res.json() as Promise<BatchExportRunsResponse>)
            .then((data) => {
                setExportRuns(data.results)
                setLoading(false)
            })
            .catch((error) => {
                setError(error)
                setLoading(false)
            })

        return () => controller.abort()
    }, [teamId, exportId])

    return { loading, exportRuns, error }
}

type BatchExportRunStatus =
    | 'Cancelled'
    | 'Completed'
    | 'ContinuedAsNew'
    | 'Failed'
    | 'Terminated'
    | 'TimedOut'
    | 'Running'
    | 'Starting'

type BatchExportRun = {
    id: string
    team_id: number
    status: BatchExportRunStatus
    opened_at: string
    closed_at: string
    data_interval_start: string
    data_interval_end: string
    created_at: string
    last_updated_at: string
}

type BatchExportRunsResponse = {
    results: BatchExportRun[]
}
