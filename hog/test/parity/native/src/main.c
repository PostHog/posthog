#include "pricing.h"

int badge_width(const char *label);

int main(int argc, char **argv) {
    return apply_discount(argc * 100, argc > 2) + badge_width(argv[0]);
}
