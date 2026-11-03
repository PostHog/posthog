import { resetContext, getContext } from '../../src'

import { detachReducer, DETACH_REDUCER } from '../../src/kea/reducer'

describe('detach reducer', () => {
  beforeEach(() => {
    resetContext()
  })

  test('detaches from a simple state', () => {
    const reducer = () => {}

    getContext().reducers.tree = {
      scenes: { something: { 1: reducer } },
    }

    let dispatched = []

    getContext().store = {
      dispatch: (action) => dispatched.push(action),
    }

    detachReducer({ path: ['scenes', 'something', 1] })

    expect(getContext().reducers.tree).toEqual({ scenes: {} })
    expect(dispatched.length).toEqual(1)
    expect(dispatched[0].type).toEqual(DETACH_REDUCER)
  })

  test('detaches from a state with 2 reducers', () => {
    const reducer1 = () => {}
    const reducer2 = () => {}

    getContext().reducers.tree = {
      scenes: { something: { 1: reducer1, 2: reducer2 } },
    }

    let dispatched = []

    getContext().store = {
      dispatch: (action) => dispatched.push(action),
    }

    detachReducer({ path: ['scenes', 'something', 1] })

    expect(getContext().reducers.tree).toEqual({ scenes: { something: { 2: reducer2 } } })
    expect(dispatched.length).toEqual(1)
    expect(dispatched[0].type).toEqual(DETACH_REDUCER)

    detachReducer({ path: ['scenes', 'something', 2] })

    expect(getContext().reducers.tree).toEqual({ scenes: {} })
    expect(dispatched.length).toEqual(2)
    expect(dispatched[1].type).toEqual(DETACH_REDUCER)
  })

  test('detaches from a state with 2 nested reducers, part 1', () => {
    const reducer1 = () => {}
    const reducer2 = () => {}

    getContext().reducers.tree = {
      scenes: { something: { 1: reducer1, bla: { 2: reducer2 } } },
    }

    let dispatched = []

    getContext().store = {
      dispatch: (action) => dispatched.push(action),
    }

    detachReducer({ path: ['scenes', 'something', 'bla', 2] })

    expect(getContext().reducers.tree).toEqual({ scenes: { something: { 1: reducer1 } } })
    expect(dispatched.length).toEqual(1)
    expect(dispatched[0].type).toEqual(DETACH_REDUCER)

    detachReducer({ path: ['scenes', 'something', 1] })

    expect(getContext().reducers.tree).toEqual({ scenes: {} })
    expect(dispatched.length).toEqual(2)
    expect(dispatched[1].type).toEqual(DETACH_REDUCER)
  })

  test('detaches from a state with 2 nested reducers, part 1', () => {
    const reducer1 = () => {}
    const reducer2 = () => {}

    getContext().reducers.tree = {
      scenes: { something: { cat: { 1: reducer1 }, bla: { 2: reducer2 } } },
    }

    let dispatched = []

    getContext().store = {
      dispatch: (action) => dispatched.push(action),
    }

    detachReducer({ path: ['scenes', 'something', 'bla', 2] })

    expect(getContext().reducers.tree).toEqual({ scenes: { something: { cat: { 1: reducer1 } } } })
    expect(dispatched.length).toEqual(1)
    expect(dispatched[0].type).toEqual(DETACH_REDUCER)

    detachReducer({ path: ['scenes', 'something', 'cat', 1] })

    expect(getContext().reducers.tree).toEqual({ scenes: {} })
    expect(dispatched.length).toEqual(2)
    expect(dispatched[1].type).toEqual(DETACH_REDUCER)
  })

  test('detaches from a state with a low reducer', () => {
    const reducer1 = () => {}

    getContext().reducers.tree = {
      scenes: { something: reducer1 },
    }

    let dispatched = []

    getContext().store = {
      dispatch: (action) => dispatched.push(action),
    }

    detachReducer({ path: ['scenes', 'something'] })

    expect(getContext().reducers.tree).toEqual({ scenes: {} })
    expect(dispatched.length).toEqual(1)
    expect(dispatched[0].type).toEqual(DETACH_REDUCER)
  })

  test('cleans up a nested tree, vol 1', () => {
    const reducer1 = () => {}
    const reducer2 = () => {}

    getContext().reducers.tree = {
      scenes: { something: { cat: { foo: { bar: { 1: reducer1 } } }, bla: { moo: { 2: reducer2 } } } },
    }

    let dispatched = []

    getContext().store = {
      dispatch: (action) => dispatched.push(action),
    }

    detachReducer({ path: ['scenes', 'something', 'bla', 'moo', 2] })

    expect(getContext().reducers.tree).toEqual({ scenes: { something: { cat: { foo: { bar: { 1: reducer1 } } } } } })
    expect(dispatched.length).toEqual(1)
    expect(dispatched[0].type).toEqual(DETACH_REDUCER)

    detachReducer({ path: ['scenes', 'something', 'cat', 'foo', 'bar', 1] })

    expect(getContext().reducers.tree).toEqual({ scenes: {} })
    expect(dispatched.length).toEqual(2)
    expect(dispatched[1].type).toEqual(DETACH_REDUCER)
  })

  test('cleans up a nested tree, vol 2', () => {
    const reducer1 = () => {}
    const reducer2 = () => {}

    getContext().reducers.tree = {
      scenes: { something: { cat: { foo: { bar: { 1: reducer1 } } }, bla: { moo: { 2: reducer2 } } } },
    }

    let dispatched = []

    getContext().store = {
      dispatch: (action) => dispatched.push(action),
    }

    detachReducer({ path: ['scenes', 'something', 'cat', 'foo', 'bar', 1] })

    expect(getContext().reducers.tree).toEqual({ scenes: { something: { bla: { moo: { 2: reducer2 } } } } })
    expect(dispatched.length).toEqual(1)
    expect(dispatched[0].type).toEqual(DETACH_REDUCER)

    detachReducer({ path: ['scenes', 'something', 'bla', 'moo', 2] })

    expect(getContext().reducers.tree).toEqual({ scenes: {} })
    expect(dispatched.length).toEqual(2)
    expect(dispatched[1].type).toEqual(DETACH_REDUCER)
  })
})
