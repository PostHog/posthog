import { MaterializedColumnSlotState } from './materializedColumnsLogic'

// DMAT uses a single string-only column pool; HogQL casts to the property's
// logical type at read time (typed dmat_* columns were removed).
export function dmatColumnName(slotIndex: number): string {
    return `dmat_string_${slotIndex}`
}

export const STATE_TOOLTIP: Record<MaterializedColumnSlotState, string> = {
    [MaterializedColumnSlotState.PENDING]:
        'Queued. The next weekly backfill cycle will assign a column and start the historical backfill.',
    [MaterializedColumnSlotState.BACKFILL]:
        'New events are populating the column; historical events are being backfilled. Queries still use JSON until READY.',
    [MaterializedColumnSlotState.READY]: 'Active — HogQL reads from the materialized column.',
    [MaterializedColumnSlotState.ERROR]:
        'Backfill failed. Click "Retry" to put it back in the queue for the next cycle.',
}
