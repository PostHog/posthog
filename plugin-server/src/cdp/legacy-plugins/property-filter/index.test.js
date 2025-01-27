const { createEvent } = require('@posthog/plugin-scaffold/test/utils')
const { processEvent } = require('.')

const global = {
    propertiesToFilter: [
        'gender',
        '$set.gender',
        '$set.age',
        'foo.bar.baz.one',
        'nonExisting',
        '$set.$not_in_props',
        'no-such.with-dot',
]}

const properties = {
    properties: {
        name: 'Mr. Hog',
        gender: 'male',
        age: 12,
        $set: {
            age: 35,
            pet: 'dog',
            firstName: 'Post',
            gender: 'female',
        },
        foo: {
            bar: {
                baz: {
                    one: 'one',
                    two: 'two',
                },
            },
        },
    },
}

test('event properties are filtered', async () => {
    const event = await processEvent(createEvent(properties), { global })
    expect(event.properties).not.toHaveProperty('gender')
    expect(event.properties.$set).not.toHaveProperty('age')
    expect(event.properties.foo.bar.baz).not.toHaveProperty('one')
    expect(event.properties).toHaveProperty('name')
    expect(event.properties).toHaveProperty('$set')
    expect(event.properties).toHaveProperty('foo')
    expect(event.properties.$set).toHaveProperty('firstName', 'Post')
    expect(event.properties.foo.bar.baz).toHaveProperty('two', 'two')
    expect(event.properties).toEqual(
    {
        name: 'Mr. Hog',
        age: 12,
        $set: {
            pet: 'dog',
            firstName: 'Post',
        },
        foo: {
            bar: {
                baz: {
                    two: 'two',
                },
            },
        },
    })
})

const emptyProperties = {}

test('event properties are empty when no properties are given', async () => {
    const event = await processEvent(createEvent(emptyProperties), { global })

    expect(event.properties).not.toHaveProperty('$set')
    expect(event.properties).not.toHaveProperty('foo')
})
