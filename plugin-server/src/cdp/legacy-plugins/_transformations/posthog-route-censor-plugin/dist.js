'use strict'

const checkIsValidHttpUrl = (str) => {
    try {
        const url = new URL(str)
        return url.protocol === 'http:' || url.protocol === 'https:'
    } catch (err) {
        return false
    }
}

/**
 * @remix-run/router v1.5.0
 *
 * Copyright (c) Remix Software Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE.md file in the root directory of this source tree.
 *
 * @license MIT
 */

////////////////////////////////////////////////////////////////////////////////
//#region Types and Constants
////////////////////////////////////////////////////////////////////////////////

/**
 * Actions represent the type of change to a location value.
 */
var Action
;(function (Action) {
    /**
     * A POP indicates a change to an arbitrary index in the history stack, such
     * as a back or forward navigation. It does not describe the direction of the
     * navigation, only that the current index changed.
     *
     * Note: This is the default action for newly created history objects.
     */
    Action['Pop'] = 'POP'
    /**
     * A PUSH indicates a new entry being added to the history stack, such as when
     * a link is clicked and a new page loads. When this happens, all subsequent
     * entries in the stack are lost.
     */

    Action['Push'] = 'PUSH'
    /**
     * A REPLACE indicates the entry at the current index in the history stack
     * being replaced by a new one.
     */

    Action['Replace'] = 'REPLACE'
})(Action || (Action = {}))
function invariant(value, message) {
    if (value === false || value === null || typeof value === 'undefined') {
        throw new Error(message)
    }
}
function warning(cond, message) {
    if (!cond) {
        try {
            // Welcome to debugging history!
            //
            // This error is thrown as a convenience so you can more easily
            // find the source for a warning that appears in the console by
            // enabling "pause on exceptions" in your JavaScript debugger.
            throw new Error(message)
        } catch (e) {}
    }
}
/**
 * Parses a string URL path into its separate pathname, search, and hash components.
 */

function parsePath(path) {
    let parsedPath = {}

    if (path) {
        let hashIndex = path.indexOf('#')

        if (hashIndex >= 0) {
            parsedPath.hash = path.substr(hashIndex)
            path = path.substr(0, hashIndex)
        }

        let searchIndex = path.indexOf('?')

        if (searchIndex >= 0) {
            parsedPath.search = path.substr(searchIndex)
            path = path.substr(0, searchIndex)
        }

        if (path) {
            parsedPath.pathname = path
        }
    }

    return parsedPath
}

var ResultType
;(function (ResultType) {
    ResultType['data'] = 'data'
    ResultType['deferred'] = 'deferred'
    ResultType['redirect'] = 'redirect'
    ResultType['error'] = 'error'
})(ResultType || (ResultType = {}))
/**
 * Matches the given routes to a location and returns the match data.
 *
 * @see https://reactrouter.com/utils/match-routes
 */

function matchRoutes(routes, locationArg, basename) {
    if (basename === void 0) {
        basename = '/'
    }

    let location = typeof locationArg === 'string' ? parsePath(locationArg) : locationArg
    let pathname = stripBasename(location.pathname || '/', basename)

    if (pathname == null) {
        return null
    }

    let branches = flattenRoutes(routes)
    rankRouteBranches(branches)
    let matches = null

    for (let i = 0; matches == null && i < branches.length; ++i) {
        matches = matchRouteBranch(
            branches[i], // Incoming pathnames are generally encoded from either window.location
            // or from router.navigate, but we want to match against the unencoded
            // paths in the route definitions.  Memory router locations won't be
            // encoded here but there also shouldn't be anything to decode so this
            // should be a safe operation.  This avoids needing matchRoutes to be
            // history-aware.
            safelyDecodeURI(pathname)
        )
    }

    return matches
}

function flattenRoutes(routes, branches, parentsMeta, parentPath) {
    if (branches === void 0) {
        branches = []
    }

    if (parentsMeta === void 0) {
        parentsMeta = []
    }

    if (parentPath === void 0) {
        parentPath = ''
    }

    let flattenRoute = (route, index, relativePath) => {
        let meta = {
            relativePath: relativePath === undefined ? route.path || '' : relativePath,
            caseSensitive: route.caseSensitive === true,
            childrenIndex: index,
            route,
        }

        if (meta.relativePath.startsWith('/')) {
            invariant(
                meta.relativePath.startsWith(parentPath),
                'Absolute route path "' +
                    meta.relativePath +
                    '" nested under path ' +
                    ('"' + parentPath + '" is not valid. An absolute child route path ') +
                    'must start with the combined path of all its parent routes.'
            )
            meta.relativePath = meta.relativePath.slice(parentPath.length)
        }

        let path = joinPaths([parentPath, meta.relativePath])
        let routesMeta = parentsMeta.concat(meta) // Add the children before adding this route to the array so we traverse the
        // route tree depth-first and child routes appear before their parents in
        // the "flattened" version.

        if (route.children && route.children.length > 0) {
            invariant(
                // Our types know better, but runtime JS may not!
                route.index !== true,
                'Index routes must not have child routes. Please remove ' +
                    ('all child routes from route path "' + path + '".')
            )
            flattenRoutes(route.children, branches, routesMeta, path)
        } // Routes without a path shouldn't ever match by themselves unless they are
        // index routes, so don't add them to the list of possible branches.

        if (route.path == null && !route.index) {
            return
        }

        branches.push({
            path,
            score: computeScore(path, route.index),
            routesMeta,
        })
    }

    routes.forEach((route, index) => {
        var _route$path

        // coarse-grain check for optional params
        if (route.path === '' || !((_route$path = route.path) != null && _route$path.includes('?'))) {
            flattenRoute(route, index)
        } else {
            for (let exploded of explodeOptionalSegments(route.path)) {
                flattenRoute(route, index, exploded)
            }
        }
    })
    return branches
}
/**
 * Computes all combinations of optional path segments for a given path,
 * excluding combinations that are ambiguous and of lower priority.
 *
 * For example, `/one/:two?/three/:four?/:five?` explodes to:
 * - `/one/three`
 * - `/one/:two/three`
 * - `/one/three/:four`
 * - `/one/three/:five`
 * - `/one/:two/three/:four`
 * - `/one/:two/three/:five`
 * - `/one/three/:four/:five`
 * - `/one/:two/three/:four/:five`
 */

function explodeOptionalSegments(path) {
    let segments = path.split('/')
    if (segments.length === 0) {
        return []
    }
    let [first, ...rest] = segments // Optional path segments are denoted by a trailing `?`

    let isOptional = first.endsWith('?') // Compute the corresponding required segment: `foo?` -> `foo`

    let required = first.replace(/\?$/, '')

    if (rest.length === 0) {
        // Intepret empty string as omitting an optional segment
        // `["one", "", "three"]` corresponds to omitting `:two` from `/one/:two?/three` -> `/one/three`
        return isOptional ? [required, ''] : [required]
    }

    let restExploded = explodeOptionalSegments(rest.join('/'))
    let result = [] // All child paths with the prefix.  Do this for all children before the
    // optional version for all children so we get consistent ordering where the
    // parent optional aspect is preferred as required.  Otherwise, we can get
    // child sections interspersed where deeper optional segments are higher than
    // parent optional segments, where for example, /:two would explodes _earlier_
    // then /:one.  By always including the parent as required _for all children_
    // first, we avoid this issue

    result.push(...restExploded.map((subpath) => (subpath === '' ? required : [required, subpath].join('/')))) // Then if this is an optional value, add all child versions without

    if (isOptional) {
        result.push(...restExploded)
    } // for absolute paths, ensure `/` instead of empty segment

    return result.map((exploded) => (path.startsWith('/') && exploded === '' ? '/' : exploded))
}

function rankRouteBranches(branches) {
    branches.sort((a, b) =>
        a.score !== b.score
            ? b.score - a.score // Higher score first
            : compareIndexes(
                  a.routesMeta.map((meta) => meta.childrenIndex),
                  b.routesMeta.map((meta) => meta.childrenIndex)
              )
    )
}

const paramRe = /^:\w+$/
const dynamicSegmentValue = 3
const indexRouteValue = 2
const emptySegmentValue = 1
const staticSegmentValue = 10
const splatPenalty = -2

const isSplat = (s) => s === '*'

function computeScore(path, index) {
    let segments = path.split('/')
    let initialScore = segments.length

    if (segments.some(isSplat)) {
        initialScore += splatPenalty
    }

    if (index) {
        initialScore += indexRouteValue
    }

    return segments
        .filter((s) => !isSplat(s))
        .reduce(
            (score, segment) =>
                score +
                (paramRe.test(segment) ? dynamicSegmentValue : segment === '' ? emptySegmentValue : staticSegmentValue),
            initialScore
        )
}

function compareIndexes(a, b) {
    let siblings = a.length === b.length && a.slice(0, -1).every((n, i) => n === b[i])
    return siblings // If two routes are siblings, we should try to match the earlier sibling
        ? // first. This allows people to have fine-grained control over the matching
          // behavior by simply putting routes with identical paths in the order they
          // want them tried.
          a[a.length - 1] - b[b.length - 1] // Otherwise, it doesn't really make sense to rank non-siblings by index,
        : // so they sort equally.
          0
}

function matchRouteBranch(branch, pathname) {
    let { routesMeta } = branch
    let matchedParams = {}
    let matchedPathname = '/'
    let matches = []

    for (let i = 0; i < routesMeta.length; ++i) {
        let meta = routesMeta[i]
        let end = i === routesMeta.length - 1
        let remainingPathname = matchedPathname === '/' ? pathname : pathname.slice(matchedPathname.length) || '/'
        let match = matchPath(
            {
                path: meta.relativePath,
                caseSensitive: meta.caseSensitive,
                end,
            },
            remainingPathname
        )
        if (!match) {
            return null
        }
        Object.assign(matchedParams, match.params)
        let route = meta.route
        matches.push({
            // TODO: Can this as be avoided?
            params: matchedParams,
            pathname: joinPaths([matchedPathname, match.pathname]),
            pathnameBase: normalizePathname(joinPaths([matchedPathname, match.pathnameBase])),
            route,
        })

        if (match.pathnameBase !== '/') {
            matchedPathname = joinPaths([matchedPathname, match.pathnameBase])
        }
    }

    return matches
}
/**
 * Performs pattern matching on a URL pathname and returns information about
 * the match.
 *
 * @see https://reactrouter.com/utils/match-path
 */

function matchPath(pattern, pathname) {
    if (typeof pattern === 'string') {
        pattern = {
            path: pattern,
            caseSensitive: false,
            end: true,
        }
    }

    let [matcher, paramNames] = compilePath(pattern.path, pattern.caseSensitive, pattern.end)
    let match = pathname.match(matcher)
    if (!match) {
        return null
    }
    let matchedPathname = match[0]
    let pathnameBase = matchedPathname.replace(/(.)\/+$/, '$1')
    let captureGroups = match.slice(1)
    let params = paramNames.reduce((memo, paramName, index) => {
        // We need to compute the pathnameBase here using the raw splat value
        // instead of using params["*"] later because it will be decoded then
        if (paramName === '*') {
            let splatValue = captureGroups[index] || ''
            pathnameBase = matchedPathname.slice(0, matchedPathname.length - splatValue.length).replace(/(.)\/+$/, '$1')
        }

        memo[paramName] = safelyDecodeURIComponent(captureGroups[index] || '', paramName)
        return memo
    }, {})
    return {
        params,
        pathname: matchedPathname,
        pathnameBase,
        pattern,
    }
}

function compilePath(path, caseSensitive, end) {
    if (caseSensitive === void 0) {
        caseSensitive = false
    }

    if (end === void 0) {
        end = true
    }

    warning(
        path === '*' || !path.endsWith('*') || path.endsWith('/*'),
        'Route path "' +
            path +
            '" will be treated as if it were ' +
            ('"' + path.replace(/\*$/, '/*') + '" because the `*` character must ') +
            'always follow a `/` in the pattern. To get rid of this warning, ' +
            ('please change the route path to "' + path.replace(/\*$/, '/*') + '".')
    )
    let paramNames = []
    let regexpSource =
        '^' +
        path
            .replace(/\/*\*?$/, '') // Ignore trailing / and /*, we'll handle it below
            .replace(/^\/*/, '/') // Make sure it has a leading /
            .replace(/[\\.*+^$?{}|()[\]]/g, '\\$&') // Escape special regex chars
            .replace(/\/:(\w+)/g, (_, paramName) => {
                paramNames.push(paramName)
                return '/([^\\/]+)'
            })

    if (path.endsWith('*')) {
        paramNames.push('*')
        regexpSource +=
            path === '*' || path === '/*'
                ? '(.*)$' // Already matched the initial /, just match the rest
                : '(?:\\/(.+)|\\/*)$' // Don't include the / in params["*"]
    } else if (end) {
        // When matching to the end, ignore trailing slashes
        regexpSource += '\\/*$'
    } else if (path !== '' && path !== '/') {
        // If our path is non-empty and contains anything beyond an initial slash,
        // then we have _some_ form of path in our regex so we should expect to
        // match only if we find the end of this path segment.  Look for an optional
        // non-captured trailing slash (to match a portion of the URL) or the end
        // of the path (if we've matched to the end).  We used to do this with a
        // word boundary but that gives false positives on routes like
        // /user-preferences since `-` counts as a word boundary.
        regexpSource += '(?:(?=\\/|$))'
    } else {
    }

    let matcher = new RegExp(regexpSource, caseSensitive ? undefined : 'i')
    return [matcher, paramNames]
}

function safelyDecodeURI(value) {
    try {
        return decodeURI(value)
    } catch (error) {
        warning(
            false,
            'The URL path "' +
                value +
                '" could not be decoded because it is is a ' +
                'malformed URL segment. This is probably due to a bad percent ' +
                ('encoding (' + error + ').')
        )
        return value
    }
}

function safelyDecodeURIComponent(value, paramName) {
    try {
        return decodeURIComponent(value)
    } catch (error) {
        warning(
            false,
            'The value for the URL param "' +
                paramName +
                '" will not be decoded because' +
                (' the string "' + value + '" is a malformed URL segment. This is probably') +
                (' due to a bad percent encoding (' + error + ').')
        )
        return value
    }
}
/**
 * @private
 */

function stripBasename(pathname, basename) {
    if (basename === '/') {
        return pathname
    }

    if (!pathname.toLowerCase().startsWith(basename.toLowerCase())) {
        return null
    } // We want to leave trailing slash behavior in the user's control, so if they
    // specify a basename with a trailing slash, we should support it

    let startIndex = basename.endsWith('/') ? basename.length - 1 : basename.length
    let nextChar = pathname.charAt(startIndex)

    if (nextChar && nextChar !== '/') {
        // pathname does not start with basename/
        return null
    }

    return pathname.slice(startIndex) || '/'
}
/**
 * @private
 */

const joinPaths = (paths) => paths.join('/').replace(/\/\/+/g, '/')
/**
 * @private
 */

const normalizePathname = (pathname) => pathname.replace(/\/+$/, '').replace(/^\/*/, '/')

const validMutationMethodsArr = ['post', 'put', 'patch', 'delete']
;['get', ...validMutationMethodsArr]

/**
 * Take a URL path and applies the react router v6 route matching algorithm
 * to censor portions of the URL
 *
 * @param path URL path to censor
 * @returns same URL path, but with all included variables censored
 */
const censorUrlPath = (path, routes) => {
    if (typeof path !== 'string') {
        return path
    }
    // If no routes, then just censor all paths to be safe.
    if (typeof routes === 'undefined') {
        return '/:censoredFullPath'
    }
    // Find matches with URL path using React Router's parsing algoritm.
    const matches = matchRoutes(routes, path)
    // If no matches, then no need to censor anything.
    if (!matches?.length) {
        return path
    }
    let censoredPath = path
    // Check each match, if the variable is in the "includes" array, then censor it.
    matches.forEach((match) => {
        match.route.include.forEach((variableToCensor) => {
            const value = match.params[variableToCensor]
            if (!value) {
                return
            }
            censoredPath = censoredPath.replace(value, `:${variableToCensor}`)
        })
    })
    return censoredPath
}

/**
 * Removes addresses and hashes from URLs stored in posthog properties.
 *
 * @param properties Full list of properties passed into the event.
 * @param propertiesToAnonymize List of properties that should be anonymized.
 * @returns The anonymized list of properties.
 */
const censorProperties = (properties, routes, propertiesToAnonymize) => {
    if (!properties) {
        return {}
    }
    const censoredProperties = {}
    propertiesToAnonymize.forEach((propertyKey) => {
        const propertyValue = properties[propertyKey]
        if (!propertyValue || typeof propertyValue !== 'string') {
            return
        }
        const isValidUrl = checkIsValidHttpUrl(propertyValue)
        // For full URLs, first parse out the path.
        if (isValidUrl) {
            const url = new URL(propertyValue)
            const censoredPath = censorUrlPath(url.pathname, routes)
            // Piece back together the URL but with the censored path.
            censoredProperties[propertyKey] = `${url.origin}${censoredPath}`
            return
        }
        // Otherwise assume the propertyValue is a url path (instead of the full url) and we can censor it directly.
        censoredProperties[propertyKey] = censorUrlPath(propertyValue, routes)
    })
    return censoredProperties
}

/**
 * Runs on every event
 *
 * @param event PostHog event
 * @param meta metadata defined in the plugin.json
 * @returns modified event
 */
const processEvent = (event, { global }) => {
    // If we don't have routes to censor, then just return the input event.
    if (!global.routes?.length) {
        return event
    }
    return {
        ...event,
        properties: {
            ...event.properties,
            ...censorProperties(event.properties, global.routes, global.properties),
        },
        $set: {
            ...event.$set,
            ...censorProperties(event.$set, global.routes, global.setProperties),
        },
        $set_once: {
            ...event.$set_once,
            ...censorProperties(event.$set_once, global.routes, global.setOnceProperties),
        },
    }
}

exports.processEvent = processEvent
