package com.example.backend.model;

import lombok.NoArgsConstructor;

import java.util.Objects;

public class KeyMap {
    public float x;
    public int y;
    public boolean fixed;

    public KeyMap(float x, int y, boolean fixed) {
        this.x = x;
        this.y = y;
        this.fixed = fixed;
    }

    public KeyMap() {

    }

    public float getX() { return x; }
    public int getY() { return y; }
    public boolean isFixed() { return fixed; }

    // "with" methods for convenient immutability
    public KeyMap withX(float newX)       { return new KeyMap(newX, y, fixed); }
    public KeyMap withY(int newY)         { return new KeyMap(x, newY, fixed); }
    public KeyMap withFixed(boolean b)    { return new KeyMap(x, y, b); }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof KeyMap)) return false;
        KeyMap k = (KeyMap) o;
        return Float.compare(k.x, x) == 0
                && y == k.y
                && fixed == k.fixed;
    }

    @Override
    public int hashCode() {
        return Objects.hash(Float.hashCode(x), y, fixed);
    }

    @Override
    public String toString() {
        return "KeyMap{x=" + x + ", y=" + y + ", fixed=" + fixed + '}';
    }
}
