import { dayjs } from 'lib/dayjs'
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

export const useExports = (
    teamId: number
): {
    exportsState: UseExportsReturnType
    updateCallback: (signal: AbortSignal | undefined) => void
} => {
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

    const updateCallback = useCallback(
        (signal: AbortSignal | undefined) => {
            fetch(`/api/projects/${teamId}/batch_exports/`, { signal })
                .then((response) => response.json() as Promise<BatchExportsResponse>)
                .then((data) => {
                    setExports({ loading: false, exports: data.results, error: undefined })
                })
                .catch((error) => {
                    setExports({ loading: false, exports: undefined, error })
                })
        },
        [teamId]
    )

    // Make the actual fetch request as a side effect.
    useEffect(() => {
        const controller = new AbortController()
        const signal = controller.signal

        updateCallback(signal)

        return () => controller.abort()
    }, [teamId])

    return { exportsState: state, updateCallback }
}

type S3Destination = {
    // At the moment we just support S3, but we include this nesting to
    // allow for future expansion easily without needing to change the
    // interface.
    type: 'S3'
    config: {
        bucket_name: string
        region: string
        prefix: string
        aws_access_key_id: string
        aws_secret_access_key: string
    }
}

type SnowflakeDestination = {
    type: 'Snowflake'
    config: {
        account: string
        database: string
        warehouse: string
        user: string
        password: string
        schema: string
        table_name: string
    }
}

export type Destination = S3Destination | SnowflakeDestination

export type BatchExportData = {
    // User provided data for the export. This is the data that the user
    // provides when creating the export.
    name: string
    destination: Destination
    interval: 'hour' | 'day'
    start_at: string | null
    end_at: string | null
}

export type BatchExport = {
    id: string
    team_id: number
    status: 'RUNNING' | 'FAILED' | 'COMPLETED' | 'PAUSED'
    created_at: string
    last_updated_at: string
    paused: boolean
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

export const useDeleteExport = (
    teamId: number,
    exportId: string
): {
    deleteExport: () => Promise<void>
    deleting: boolean
    error: Error | null
} => {
    // Return a callback that can be used to delete an export. We also include
    // the deleting state and error. We take a callback to update any state after delete.
    const [state, setState] = useState<{ deleting: boolean; error: Error | null }>({
        deleting: false,
        error: null,
    })

    const deleteExport = useCallback(() => {
        setState({ deleting: true, error: null })
        return api.delete(`/api/projects/${teamId}/batch_exports/${exportId}`).then((response) => {
            if (response.ok) {
                setState({ deleting: false, error: null })
            } else {
                // TODO: parse the error response.
                const error = new Error(response.statusText)
                setState({ deleting: false, error: error })
                throw error
            }
        })
    }, [teamId, exportId])

    return { deleteExport, ...state }
}

export const useExportAction = (
    teamId: number,
    exportId: string,
    action: 'pause' | 'unpause'
): {
    executeExportAction: (data: any) => Promise<void>
    loading: boolean
    error: Error | null
} => {
    // Returns a callback to execute an action for the given team and export ID.
    const [state, setState] = useState<{ loading: boolean; error: Error | null }>({ loading: false, error: null })

    const executeExportAction = useCallback(
        (data) => {
            setState({ loading: true, error: null })
            return api
                .createResponse(`/api/projects/${teamId}/batch_exports/${exportId}/${action}`, data ? data : {})
                .then((response) => {
                    if (response.ok) {
                        setState({ loading: false, error: null })
                    } else {
                        // TODO: parse the error response.
                        const error = new Error(response.statusText)
                        setState({ loading: false, error: error })
                        throw error
                    }
                })
        },
        [teamId, exportId, action]
    )

    return { executeExportAction, ...state }
}

export const useExport = (
    teamId: number,
    exportId: string
): {
    loading: boolean
    export_: BatchExport | undefined
    error: Error | undefined
    updateCallback: (signal: AbortSignal | undefined) => void
} => {
    // Fetches the export details for the given team and export ID.
    const [loading, setLoading] = useState(true)
    const [export_, setExport] = useState<BatchExport>()
    const [error, setError] = useState<Error>()

    const updateCallback = useCallback(
        (signal: AbortSignal | undefined) => {
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
        },
        [teamId, exportId]
    )

    useEffect(() => {
        const controller = new AbortController()
        const signal = controller.signal

        setLoading(true)
        setError(undefined)

        updateCallback(signal)

        return () => controller.abort()
    }, [teamId, exportId])

    return { loading, export_, error, updateCallback }
}

export const useExportRuns = (
    teamId: number,
    exportId: string,
    limit: number | null,
    dateRange: [dayjs.Dayjs, dayjs.Dayjs]
): {
    loading: boolean
    exportRuns: BatchExportRun[] | undefined
    error: Error | undefined
    updateCallback: (
        signal: AbortSignal | undefined,
        numberOfRows: number | null,
        dateRange: [dayjs.Dayjs, dayjs.Dayjs]
    ) => Promise<void>
} => {
    // Fetches the export runs for the given team and export ID.
    const [loading, setLoading] = useState(true)
    const [exportRuns, setExportRuns] = useState<BatchExportRun[]>()
    const [error, setError] = useState<Error>()

    const updateCallback = useCallback(
        (signal: AbortSignal | undefined, numberOfRows: number | null, dateRange: [dayjs.Dayjs, dayjs.Dayjs]) => {
            setLoading(true)
            setError(undefined)

            const url = numberOfRows
                ? `/api/projects/${teamId}/batch_exports/${exportId}/runs?limit=${encodeURIComponent(
                      numberOfRows
                  )}&after=${encodeURIComponent(dateRange[0].toISOString())}&before=${encodeURIComponent(
                      dateRange[1].toISOString()
                  )}`
                : `/api/projects/${teamId}/batch_exports/${exportId}/runs?after=${encodeURIComponent(
                      dateRange[0].toISOString()
                  )}&before=${encodeURIComponent(dateRange[1].toISOString())}`

            return fetch(url, { signal })
                .then((res) => res.json() as Promise<BatchExportRunsResponse>)
                .then((data) => {
                    setExportRuns(data.results)
                    setLoading(false)
                })
                .catch((error) => {
                    setError(error)
                    setLoading(false)
                })
        },
        [teamId, exportId]
    )

    useEffect(() => {
        const controller = new AbortController()
        const signal = controller.signal

        updateCallback(signal, limit, dateRange)

        return () => controller.abort()
    }, [teamId, exportId, limit, dateRange])

    return { loading, exportRuns, error, updateCallback }
}

export const useExportRunAction = (
    teamId: number,
    exportId: string,
    exportRunId: string,
    action: 'reset'
): {
    executeExportRunAction: () => Promise<void>
    loading: boolean
    error: Error | null
} => {
    // Returns a callback to execute an action for the given team, export ID and export run ID.
    const [state, setState] = useState<{ loading: boolean; error: Error | null }>({ loading: false, error: null })

    const executeExportRunAction = useCallback(() => {
        setState({ loading: true, error: null })
        return api
            .createResponse(`/api/projects/${teamId}/batch_exports/${exportId}/runs/${exportRunId}/${action}`, {})
            .then((response) => {
                if (response.ok) {
                    setState({ loading: false, error: null })
                } else {
                    // TODO: parse the error response.
                    const error = new Error(response.statusText)
                    setState({ loading: false, error: error })
                    throw error
                }
            })
    }, [teamId, exportId, action])

    return { executeExportRunAction, ...state }
}

export type BatchExportRunStatus =
    | 'Cancelled'
    | 'Completed'
    | 'ContinuedAsNew'
    | 'Failed'
    | 'Terminated'
    | 'TimedOut'
    | 'Running'
    | 'Starting'

export type BatchExportRun = {
    id: string
    team_id: number
    batch_export_id: string
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
