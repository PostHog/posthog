/**
 * Cohort membership functions for HogVM
 */

/**
 * Check if a cohort ID is in a list of cohort IDs
 *
 * @param args Array where:
 *   args[0] = The cohort ID to check for (from bytecode)
 *   args[1] = List of cohort IDs the person belongs to (from runtime)
 * @returns true if cohort ID is in the person's cohort list, false otherwise
 */
export function inCohort(args: any[]): boolean {
    if (args.length < 2) {
        return false
    }

    const cohortId = args[0]
    const personCohorts = args[1]

    if (cohortId === null || cohortId === undefined || personCohorts === null || personCohorts === undefined) {
        return false
    }

    // Ensure personCohorts is an array or similar collection
    if (!Array.isArray(personCohorts) && !(personCohorts instanceof Set)) {
        return false
    }

    // Normalize cohortId - convert to int if numeric, otherwise string
    let normalizedCohortId: number | string
    if (typeof cohortId === 'number') {
        normalizedCohortId = Math.floor(cohortId)
    } else {
        normalizedCohortId = String(cohortId)
    }

    // Simple membership check with type flexibility
    for (const cid of personCohorts) {
        if (cid === null || cid === undefined) {
            continue
        }

        // Normalize each cohort ID in the list
        let normalizedCid: number | string
        if (typeof cid === 'number') {
            normalizedCid = Math.floor(cid)
        } else {
            normalizedCid = String(cid)
        }

        // Direct comparison after normalization
        if (normalizedCohortId === normalizedCid) {
            return true
        }

        // Also check string/int conversion for compatibility
        if (typeof normalizedCohortId === 'number' && typeof normalizedCid === 'string') {
            try {
                const cidAsNum = parseInt(normalizedCid, 10)
                if (!isNaN(cidAsNum) && normalizedCohortId === cidAsNum) {
                    return true
                }
            } catch {
                // Continue if conversion fails
            }
        } else if (typeof normalizedCohortId === 'string' && typeof normalizedCid === 'number') {
            if (normalizedCohortId === String(normalizedCid)) {
                return true
            }
        }
    }

    return false
}

/**
 * Check if a cohort ID is NOT in a list of cohort IDs
 *
 * @param args Array where:
 *   args[0] = The cohort ID to check for (from bytecode)
 *   args[1] = List of cohort IDs the person belongs to (from runtime)
 * @returns true if cohort ID is NOT in the person's cohort list, false otherwise
 */
export function notInCohort(args: any[]): boolean {
    return !inCohort(args)
}
