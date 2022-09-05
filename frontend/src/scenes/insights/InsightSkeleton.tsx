import React from 'react'
import { Skeleton } from 'lib/components/LemonSkeleton/LemonSkeleton'

export function InsightSkeleton(): JSX.Element {
    return (
        <>
            <div className="my-6 space-y-4">
                <Skeleton width={'25%'} />
                <Skeleton width={'50%'} repeat={3} />
                <Skeleton />
                <div className="border rounded p-6 flex items-center gap-4">
                    <div className="flex-1 space-y-2">
                        <Skeleton.Row repeat={3} />
                    </div>

                    <div className="flex-1 space-y-2">
                        <Skeleton.Row repeat={3} />
                    </div>
                </div>
                <div className="border rounded p-6" style={{ minHeight: 600 }} />
            </div>
        </>
    )
}
