/**
 * Piscina worker for executing HogVM bytecode in separate threads
 * This isolates CPU-intensive HogVM execution from the main event loop
 */

// Import execHog using correct relative path from this file
const { execHog } = require('./hog-exec')

/**
 * Worker function that executes HogVM bytecode
 * @param {Object} params - Execution parameters
 * @param {any} params.bytecode - HogVM bytecode to execute
 * @param {Object} params.globals - Global variables for execution context
 * @param {number} params.timeout - Execution timeout in milliseconds
 * @param {boolean} params.telemetry - Whether to collect telemetry
 * @returns {Promise<Object>} Execution result
 */
module.exports = async function executeHogWorker(params) {
    const { bytecode, globals, timeout = 550, telemetry = false } = params

    try {
        // Execute the HogVM bytecode in this worker thread
        const result = await execHog(bytecode, {
            globals,
            timeout,
            telemetry,
        })

        return {
            success: true,
            result,
        }
    } catch (error) {
        // Return error details that can be serialized across thread boundary
        return {
            success: false,
            error: {
                message: error.message,
                name: error.name,
                stack: error.stack,
            },
        }
    }
}
