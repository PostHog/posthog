class Test {
    private map = new Map<string, number>()

    constructor() {
        this.map = new Map<string, number>()
    }

    public add(key: string, value: number) {
        this.map.set(key, value)
    }

    createChild(s: string) {
        return new Child(this.map, s)
    }

    getMap() {
        return this.map
    }
}

class Child {
    constructor(private map: Map<string, number>, private s: string) {}

    public inc() {
        this.map.set(this.s, (this.map.get(this.s) || 0) + 1)
    }
}

const t = new Test()

const child = t.createChild('test')
child.inc()
child.inc()

const child2 = t.createChild('test2')
child2.inc()

t.add('test3', 1)

console.log(t.getMap())
