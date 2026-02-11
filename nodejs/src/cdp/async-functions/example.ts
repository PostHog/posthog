import { DateTime } from 'luxon'

import { registerAsyncFunction } from '../async-function-registry'

/**
 * Example of an async function that performs a fetch request. Once an async function has been registered, it can be called from a HogFunction.
 *
 * If you're adding a new destination or workflow action that will use your async function, these are defined in nodejs/src/cdp/templates/_destinations.
 *
 * IMPORTANT: For your async function to be registered, it must be imported in the index.ts file in this directory (nodejs/src/cdp/async-functions/index.ts)
 */

registerAsyncFunction('foobar', {
    /**
     *
     * @param args the arguments passed from the Hog code, for example `foobar('i am foo', {'key': 'i am bar'}, 'i am baz')`
     * @param _context includes the invocation details, any global variables attached to the invocation, and a reference to
     *   the HogExecutorServiceHub which provides access to other services and data (e.g. teamManager, featureFlagManager, etc.)
     * @param _result the current state of the invocation result, which can be modified by the async function and serves as a place to store
     *   its return value and/or modify the invocation.
     *   For example, you can set a value for a key on result.invocation, and that value would then be accessible in subsequent async functions.
     *   You can stop execution after an error by setting result.finished = true + result.error, and you can log messages to the
     *   invocation logs by pushing to result.logs. See `CyclotronJobInvocationResult` for more details on the structure of the result object.
     */
    execute: (args, _context, _result) => {
        const [foo, bar, baz] = args as [string | undefined, Record<string, any> | undefined, string | undefined]

        // Do something with the argument - this can be a fetch request, a database query, or any other asynchronous operation
        console.log(
            `Executing async function 'foobar' with arguments: foo=${foo}, bar=${JSON.stringify(bar)}, baz=${baz}`
        )
    },
    /**
     * A mock implementation of the async function used in destinations and workflows Test tooling, when "Make real HTTP requests" is disabled.
     *
     * Important: this is NOT just for unit testing, and actually shows up in the product. Do your best to simulate the real implemenation and ensure the
     * results returned from the mock have the same structure as the real implementation, so that users can get a realistic experience when using the Test tool.
     */
    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'foobar' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `foobar('${args[0]}', ${JSON.stringify(args[1], null, 2)})`,
        })

        return {
            status: 200,
            body: {},
        }
    },
})
