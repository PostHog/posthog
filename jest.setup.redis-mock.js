jest.mock('ioredis', () => {
    const Redis = require('ioredis-mock')
    if (typeof Redis === 'object') {
        // the first mock is an ioredis shim because ioredis-mock depends on it
        // https://github.com/stipsan/ioredis-mock/blob/master/src/index.js#L101-L111
        return {
            Command: { _transformer: { argument: {}, reply: {} } },
        }
    }
    // second mock for our code
    return function (...args) {
        const redis = new Redis(args)
        redis.brpop = async (...args) => {
            args.pop()
            return [args[0], await redis.rpop(...args)]
        }
        return redis
    }
})
