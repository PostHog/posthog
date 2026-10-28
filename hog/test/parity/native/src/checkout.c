#include "pricing.h"

int checkout(int cents, int quantity) {
    return apply_discount(cents * quantity, quantity > 10);
}

void _start(void) {
    volatile int total = checkout(1250, 3);
    (void)total;
    for (;;) {
    }
}
